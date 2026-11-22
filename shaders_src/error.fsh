void main()
{
	mediump float x = floor(gl_FragCoord.x / 10.0) * 0.5;
	mediump float y = floor(gl_FragCoord.y / 10.0) * 0.5;
	
	lowp vec3 c = vec3(0.0);

	if (((x - floor(x)) > 0.1) == ((y - floor(y)) > 0.1))
	{
		c = vec3(0.0, 1.0, 1.0);
	}

	gl_FragColor = vec4(c, 1.0);
}
