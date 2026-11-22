
#ifndef ENABLE_SHADER_FEATURES

//No dash-specific shader; no cubemap on dash
#ifdef DASH_SHADOWS
	#undef DASH_SHADOWS

	#ifdef CUBE_MAP
	#undef CUBE_MAP
	#endif
#else
	#ifndef CUBE_MAP
	#define CUBE_MAP
	#endif
#endif

#ifdef DONT_USE_CAR_REFLECTION //~???
	#ifdef CUBE_MAP
	#undef CUBE_MAP
	#endif
#endif

//#ifdef FOG
//	#undef FOG
//#endif

// HD remaster: keep the full per-pixel specular / normal-map path
// on the low-LOD car too (stock code undefs all four).

#endif//ENABLE_SHADER_FEATURES

//%include carv.xsh

