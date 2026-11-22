//
//  dof_discard.fsh
//
//  Created by bend on 09/01/14.
//  Copyright EA 2014. All rights reserved.
//

precision mediump float;

uniform lowp sampler2D s_Texture0;		// Diffuse texture
varying mediump vec2 v_TexCoord0;

void main()
{
	lowp vec4 diffuseTexture = texture2DWithBias( s_Texture0, v_TexCoord0 );

	if( diffuseTexture.a < 0.75 )
	{
		discard;
	}

	gl_FragColor = diffuseTexture;
}

